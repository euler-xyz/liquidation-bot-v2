// SPDX-License-Identifier: UNLICENSED
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

    bytes32 public constant HANDLER_ONE_INCH = bytes32("1Inch");
    bytes32 public constant HANDLER_UNISWAP_AUTOROUTER = bytes32("UniswapAutoRouter");

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
        uint256 swapAmount;
        uint256 expectedRemainingCollateral;
        uint256 swapType;
        bytes swapData;
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

    function liquidateSingleCollateral(LiquidationParams calldata params) external returns (bool success) {
        bytes[] memory multicallItems = new bytes[](3);

        // Calls swap function of swapper which will swap some amount of seized collateral for borrowed asset
        // Swaps via 1inch
        if (params.swapType == 1){
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                ISwapper.SwapParams({
                    handler: HANDLER_ONE_INCH,
                    mode: 0,
                    account: address(0), // ignored
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: 0,
                    vaultIn: address(0), // ignored
                    receiver: address(0), // ignored
                    data: params.swapData
                })
            );
        } else {
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                    ISwapper.SwapParams({
                    handler: HANDLER_UNISWAP_AUTOROUTER,
                    mode: 1,
                    account: swapperAddress,
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: params.repayAmount,
                    vaultIn: params.collateralVault,    
                    receiver: swapperAddress,
                    data: params.swapData
                })
            );
        }

        // Use swapper contract to repay borrowed asset
        multicallItems[1] =
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[2] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](6);

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

        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, 0) // TODO: adjust minimum collateral
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.withdraw, (params.swapAmount, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: transfer remaining collateral shares to receiver
        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(
                IERC20.transfer,
                (params.receiver, (params.seizedCollateralAmount - params.swapAmount)))
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

    function liquidateSingleCollateralWithPythOracle(LiquidationParams calldata params, bytes[] calldata pythUpdateData) external payable returns (bool success) {
        bytes[] memory multicallItems = new bytes[](3);

        // Calls swap function of swapper which will swap some amount of seized collateral for borrowed asset
        // Swaps via 1inch
        if (params.swapType == 1){
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                ISwapper.SwapParams({
                    handler: HANDLER_ONE_INCH,
                    mode: 0,
                    account: address(0), // ignored
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: 0,
                    vaultIn: address(0), // ignored
                    receiver: address(0), // ignored
                    data: params.swapData
                })
            );
        } else {
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                    ISwapper.SwapParams({
                    handler: HANDLER_UNISWAP_AUTOROUTER,
                    mode: 1,
                    account: swapperAddress,
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: params.repayAmount,
                    vaultIn: params.collateralVault,    
                    receiver: swapperAddress,
                    data: params.swapData
                })
            );
        }

        // Use swapper contract to repay borrowed asset
        multicallItems[1] =
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[2] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](7);

        // Step 0: update Pyth oracles
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: PYTH,
            value: msg.value,
            data: abi.encodeCall(IPyth.updatePriceFeeds, pythUpdateData)
        });

        // Step 1: enable controller
        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        // Step 2: enable collateral
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        // Step 3: Liquidate account in violation
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, 0) // TODO: adjust minimum collateral
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.withdraw, (params.swapAmount, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: transfer remaining collateral shares to receiver
        batchItems[6] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(
                IERC20.transfer,
                (params.receiver, (params.seizedCollateralAmount - params.swapAmount)))
        });

        // Submit batch to EVC
        evc.batch{value: msg.value}(batchItems);

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

    function liquidateSingleCollateralWithRedstoneOracle(LiquidationParams calldata params, bytes[] calldata redstoneUpdateData, address[] calldata adapterAddresses) external payable returns (bool success) {
        bytes[] memory multicallItems = new bytes[](3);

        // Calls swap function of swapper which will swap some amount of seized collateral for borrowed asset
        // Swaps via 1inch
        if (params.swapType == 1){
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                ISwapper.SwapParams({
                    handler: HANDLER_ONE_INCH,
                    mode: 0,
                    account: address(0), // ignored
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: 0,
                    vaultIn: address(0), // ignored
                    receiver: address(0), // ignored
                    data: params.swapData
                })
            );
        } else {
            multicallItems[0] = abi.encodeCall(
                ISwapper.swap,
                    ISwapper.SwapParams({
                    handler: HANDLER_UNISWAP_AUTOROUTER,
                    mode: 1,
                    account: swapperAddress,
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: params.repayAmount,
                    vaultIn: params.collateralVault,    
                    receiver: swapperAddress,
                    data: params.swapData
                })
            );
        }

        // Use swapper contract to repay borrowed asset
        multicallItems[1] =
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[2] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, params.receiver));

        uint256 numberOfOracleUpdates = redstoneUpdateData.length;

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](numberOfOracleUpdates + 6);

        // Step 0: update Redstone oracles
        for (uint256 i = 0; i < redstoneUpdateData.length; i++){
            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: adapterAddresses[i],
                value: 0,
                data: redstoneUpdateData[i]
            });
        }

        // Step 1: enable controller
        batchItems[numberOfOracleUpdates] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        // Step 2: enable collateral
        batchItems[numberOfOracleUpdates + 1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        // Step 3: Liquidate account in violation
        batchItems[numberOfOracleUpdates + 2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, 0) // TODO: adjust minimum collateral
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[numberOfOracleUpdates + 3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.withdraw, (params.swapAmount, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[numberOfOracleUpdates + 4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: transfer remaining collateral shares to receiver
        batchItems[numberOfOracleUpdates + 5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(
                IERC20.transfer,
                (params.receiver, (params.seizedCollateralAmount - params.swapAmount)))
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

        (collateralValue, liabilityValue) = abi.decode(batchItemsResult[1].result, (uint256, uint256));

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

        (maxRepay, seizedCollateral) = abi.decode(batchItemsResult[1].result, (uint256, uint256));

        return (maxRepay, seizedCollateral);
    }

    receive() external payable {

    }
}
