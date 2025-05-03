// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626, IERC20} from "./IEVault.sol";
import {IEVault, IRiskManager, IBorrowing, ILiquidation} from "./IEVault.sol";

import {IPyth} from "./IPyth.sol";

contract Liquidator {
    address public immutable owner;
    address public immutable swapperAddress;
    address public immutable swapVerifierAddress;
    address public immutable evcAddress;

    address public immutable PYTH;

    bytes32 public constant HANDLER_GENERIC = bytes32("Generic");
    bytes32 public constant HANDLER_UNISWAP_V2 = bytes32("UniswapV2");

    address public constant ONE_INCH_AGGREGATOR = 0x111111125421cA6dc452d289314280a0f8842A65;

    uint256 internal constant MODE_EXACT_IN = 0;
    uint256 internal constant MODE_EXACT_OUT = 1;

    ISwapper swapper;
    IEVC evc;

    error Unauthorized();
    error LessThanExpectedCollateralReceived();

    constructor(address _owner, address _swapperAddress, address _swapVerifierAddress, address _evcAddress, address _pythAddress) {
        owner = _owner;
        swapperAddress = _swapperAddress;
        swapVerifierAddress = _swapVerifierAddress;
        evcAddress = _evcAddress;
        PYTH = _pythAddress;

        swapper = ISwapper(_swapperAddress);
        evc = IEVC(_evcAddress);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Unauthorized");
        _;
    }

    struct LiquidationParams {
        address violatorAddress;
        address vault;
        address borrowedAsset;
        address collateralVault;
        address collateralAsset;
        uint256 repayAmount;
        uint256 seizedCollateralAmount;
        address receiver;
    }

    event Liquidation(
        address indexed violatorAddress,
        address indexed vault,
        address repaidBorrowAsset,
        address seizedCollateralAsset,
        uint256 amountRepaid,
        uint256 amountCollaterallSeized
    );

    function liquidateSingleCollateral(LiquidationParams calldata params, bytes[] calldata swapperData) external returns (bool success) {
        bytes[] memory multicallItems = new bytes[](swapperData.length + 2);

        for (uint256 i = 0; i < swapperData.length; i++){
            multicallItems[i] = swapperData[i];
        }

        // Use swapper contract to repay borrowed asset
        multicallItems[swapperData.length] =
            // abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, type(uint256).max, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[swapperData.length + 1] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](7);

        // Step 1: enable controller
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        // Step 2: enable collateral
        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        (uint256 maxRepay, uint256 maxYield) = ILiquidation(params.vault).checkLiquidation(address(this), params.violatorAddress, params.collateralVault);
        // maxYield = IERC4626(params.collateralVault).convertToAssets(maxYield);
        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, maxRepay, 0) // TODO: adjust minimum collateral
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.redeem, (maxYield, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(IRiskManager.disableController, ())
        });

        batchItems[6] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.disableCollateral, (address(this), params.collateralVault))
        });


        // Submit batch to EVC
        evc.batch(batchItems);

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        if (IERC20(params.collateralVault).balanceOf(address(this)) > 0) {
            IERC20(params.collateralVault).transfer(params.receiver, IERC20(params.collateralVault).balanceOf(address(this)));
        }

        return true;
    }

    function liquidateSingleCollateralWithPythOracle(LiquidationParams calldata params, bytes[] calldata swapperData, bytes[] calldata pythUpdateData) external payable returns (bool success) {
        bytes[] memory multicallItems = new bytes[](swapperData.length + 2);

        for (uint256 i = 0; i < swapperData.length; i++){
            multicallItems[i] = swapperData[i];
        }

        // Use swapper contract to repay borrowed asset
        multicallItems[swapperData.length] =
            // abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, type(uint256).max, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[swapperData.length + 1] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](7);

        IPyth(PYTH).updatePriceFeeds{value: msg.value}(pythUpdateData);
        // // Step 0: update Pyth oracles
        // batchItems[0] = IEVC.BatchItem({
        //     onBehalfOfAccount: address(this),
        //     targetContract: PYTH,
        //     value: msg.value,
        //     data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        // });

        // Step 1: enable controller
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        (uint256 maxRepay, uint256 maxYield) = ILiquidation(params.vault).checkLiquidation(address(this), params.violatorAddress, params.collateralVault);

        // Step 2: enable collateral
        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, maxRepay, 0) // TODO: adjust minimum collateral
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.redeem, (maxYield, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(IRiskManager.disableController, ())
        });

        batchItems[6] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.disableCollateral, (address(this), params.collateralVault))
        });


        // Submit batch to EVC
        evc.batch(batchItems);

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        if (IERC20(params.collateralVault).balanceOf(address(this)) > 0) {
            IERC20(params.collateralVault).transfer(params.receiver, IERC20(params.collateralVault).balanceOf(address(this)));
        }

        return true;
    }

    // function liquidateSingleCollateralWithRedstoneOracle(LiquidationParams calldata params,  bytes[] calldata swapperData, bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses) external payable returns (bool success) {
    //     bytes[] memory multicallItems = new bytes[](swapperData.length + 2);

    //     for (uint256 i = 0; i < swapperData.length; i++){
    //         multicallItems[i] = swapperData[i];
    //     }

    //     // Use swapper contract to repay borrowed asset
    //     multicallItems[swapperData.length] =
    //         // abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));
    //         abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, type(uint256).max, address(this)));

    //     // Sweep any dust left in the swapper contract
    //     multicallItems[swapperData.length + 1] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));
        
    //     uint256 numberOfOracleUpdates = redstoneUpdateData.length;

    //     IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](numberOfOracleUpdates + 5);

    //     // Step 0: update Redstone oracles
    //     for (uint256 i = 0; i < redstoneUpdateData.length; i++){
    //         batchItems[i] = IEVC.BatchItem({
    //             onBehalfOfAccount: address(this),
    //             targetContract: adapterAddresses[i],
    //             value: 0,
    //             data: redstoneUpdateData[i]
    //         });
    //     }

    //     // Step 1: enable controller
    //     batchItems[numberOfOracleUpdates] = IEVC.BatchItem({
    //         onBehalfOfAccount: address(0),
    //         targetContract: address(evc),
    //         value: 0,
    //         data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
    //     });

    //     // Step 2: enable collateral
    //     batchItems[numberOfOracleUpdates + 1] = IEVC.BatchItem({
    //         onBehalfOfAccount: address(0),
    //         targetContract: address(evc),
    //         value: 0,
    //         data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
    //     });

    //     (uint256 maxRepay, uint256 maxYield) = ILiquidation(params.vault).checkLiquidation(address(this), params.violatorAddress, params.collateralVault);

    //     // Step 3: Liquidate account in violation
    //     batchItems[numberOfOracleUpdates + 2] =  IEVC.BatchItem({
    //         onBehalfOfAccount: address(this),
    //         targetContract: params.vault,
    //         value: 0,
    //         data: abi.encodeCall(
    //             ILiquidation.liquidate,
    //             (params.violatorAddress, params.collateralVault, maxRepay, 0) // TODO: adjust minimum collateral
    //         )
    //     });

    //     // Step 4: Withdraw collateral from vault to swapper
    //     batchItems[numberOfOracleUpdates + 3] = IEVC.BatchItem({
    //         onBehalfOfAccount: address(this),
    //         targetContract: params.collateralVault,
    //         value: 0,
    //         data: abi.encodeCall(IERC4626.withdraw, (maxYield, swapperAddress, address(this)))
    //     });

    //     // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
    //     batchItems[numberOfOracleUpdates + 4] = IEVC.BatchItem({
    //         onBehalfOfAccount: address(this),
    //         targetContract: swapperAddress,
    //         value: 0,
    //         data: abi.encodeCall(ISwapper.multicall, multicallItems)
    //     });

    //     // Submit batch to EVC
    //     evc.batch(batchItems);

    //     emit Liquidation(
    //         params.violatorAddress,
    //         params.vault,
    //         params.borrowedAsset,
    //         params.collateralAsset,
    //         params.repayAmount,
    //         params.seizedCollateralAmount
    //     );

    //     if (IERC20(params.collateralVault).balanceOf(address(this)) > 0) {
    //         IERC20(params.collateralVault).transfer(params.receiver, IERC20(params.collateralVault).balanceOf(address(this)));
    //     }

    //     return true;
    // }

    // 2nd liquidation option: seize liquidated position without swapping/repaying, can only be done with existing collateral position
    // TODO: implement this as an operator so debt can be seized directly by whitelisted liquidators
    function liquidateFromExistingCollateralPosition(LiquidationParams calldata params)
        external
        returns (bool success)
    {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](3);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, params.seizedCollateralAmount)
            )
        });

        // batchItems[3] = IEVC.BatchItem({
        //     onBehalfOfAccount: address(this),
        //     targetContract: params.vault,
        //     value: 0,
        //     data: abi.encodeCall(
        //         IBorrowing.pullDebt(amount, from)
        //         (params.expectedRemainingCollateral, params.receiver, address(this))
        //     )
        // });

        evc.batch(batchItems);

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        return true;
    }

    function simulatePythUpdateAndGetAccountStatus(bytes[] calldata pythUpdateData, uint256 pythUpdateFee, address vaultAddress, address accountAddress) external payable returns (uint256 collateralValue, uint256 liabilityValue) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](2);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: PYTH,
            value: pythUpdateFee,
            data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(IRiskManager.accountLiquidity, (accountAddress, true))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation{value: pythUpdateFee}(batchItems);

        (collateralValue, liabilityValue) = abi.decode(batchItemsResult[1].result, (uint256, uint256));

        return (collateralValue, liabilityValue);
    }

    function simulatePythUpdateAndCheckLiquidation(bytes[] calldata pythUpdateData, uint256 pythUpdateFee, address vaultAddress, address liquidatorAddress, address borrowerAddress, address collateralAddress) external payable returns (uint256 maxRepay, uint256 seizedCollateral) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](2);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: PYTH,
            value: pythUpdateFee,
            data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(ILiquidation.checkLiquidation, (liquidatorAddress, borrowerAddress, collateralAddress))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation{value: pythUpdateFee}(batchItems);

        (maxRepay, seizedCollateral) = abi.decode(batchItemsResult[1].result, (uint256, uint256));

        return (maxRepay, seizedCollateral);
    }

    function simulateRedstoneUpdateAndGetAccountStatus(bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses, address vaultAddress, address accountAddress) external returns (uint256 collateralValue, uint256 liabilityValue) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](redstoneUpdateData.length + 1);

        for (uint256 i = 0; i < redstoneUpdateData.length; i++){
            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: adapterAddresses[i],
                value: 0,
                data: redstoneUpdateData[i]
            });
        }

        batchItems[redstoneUpdateData.length] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(IRiskManager.accountLiquidity, (accountAddress, true))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation(batchItems);

        (collateralValue, liabilityValue) = abi.decode(batchItemsResult[redstoneUpdateData.length].result, (uint256, uint256));

        return (collateralValue, liabilityValue);
    }

    function simulateRedstoneUpdateAndCheckLiquidation(bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses, address vaultAddress, address liquidatorAddress, address borrowerAddress, address collateralAddress) external payable returns (uint256 maxRepay, uint256 seizedCollateral) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](redstoneUpdateData.length + 1);

        for (uint256 i = 0; i < redstoneUpdateData.length; i++){
            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: adapterAddresses[i],
                value: 0,
                data: redstoneUpdateData[i]
            });
        }

        batchItems[redstoneUpdateData.length] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(ILiquidation.checkLiquidation, (liquidatorAddress, borrowerAddress, collateralAddress))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation(batchItems);

        (maxRepay, seizedCollateral) = abi.decode(batchItemsResult[redstoneUpdateData.length].result, (uint256, uint256));

        return (maxRepay, seizedCollateral);
    }

    function simulatePythAndRedstoneAccountStatus(bytes[] calldata pythUpdateData, uint256 pythUpdateFee, bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses, address vaultAddress, address accountAddress) external payable returns (uint256 collateralValue, uint256 liabilityValue) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](redstoneUpdateData.length + 2);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: PYTH,
            value: pythUpdateFee,
            data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        });

        for (uint256 i = 1; i < redstoneUpdateData.length; i++){
            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: adapterAddresses[i],
                value: 0,
                data: redstoneUpdateData[i]
            });
        }

        batchItems[redstoneUpdateData.length + 1] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(IRiskManager.accountLiquidity, (accountAddress, true))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation{value: pythUpdateFee}(batchItems);

        (collateralValue, liabilityValue) = abi.decode(batchItemsResult[redstoneUpdateData.length + 1].result, (uint256, uint256));

        return (collateralValue, liabilityValue);
    }

    function simulatePythAndRedstoneLiquidation(bytes[] calldata pythUpdateData, uint256 pythUpdateFee, bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses, address vaultAddress, address liquidatorAddress, address borrowerAddress, address collateralAddress) external payable returns (uint256 maxRepay, uint256 seizedCollateral) {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](redstoneUpdateData.length + 2);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: PYTH,
            value: pythUpdateFee,
            data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        });

        for (uint256 i = 1; i < redstoneUpdateData.length; i++){
            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: adapterAddresses[i],
                value: 0,
                data: redstoneUpdateData[i]
            });
        }

        batchItems[redstoneUpdateData.length + 1] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: vaultAddress,
            value: 0,
            data: abi.encodeCall(ILiquidation.checkLiquidation, (liquidatorAddress, borrowerAddress, collateralAddress))
        });

        (IEVC.BatchItemResult[] memory batchItemsResult,,) = evc.batchSimulation{value: pythUpdateFee}(batchItems);

        (maxRepay, seizedCollateral) = abi.decode(batchItemsResult[redstoneUpdateData.length + 1].result, (uint256, uint256));

        return (maxRepay, seizedCollateral);
    }

    receive() external payable {

    }
}
