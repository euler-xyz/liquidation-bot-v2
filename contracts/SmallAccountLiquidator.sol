// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626, IERC20} from "./IEVault.sol";
import {IEVault, IRiskManager, IBorrowing, ILiquidation} from "./IEVault.sol";

import {IPyth} from "./IPyth.sol";

contract Liquidator {
    address public immutable swapperAddress;
    address public immutable evcAddress;

    ISwapper swapper;
    IEVC evc;

    constructor(address _swapperAddress, address _evcAddress) {
        swapperAddress = _swapperAddress;
        evcAddress = _evcAddress;

        swapper = ISwapper(_swapperAddress);
        evc = IEVC(_evcAddress);
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

    function liquidate(LiquidationParams calldata params, bytes[] calldata swapperData, address[] calldata accounts) external returns (bool success) {
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

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](accounts.length + 5);

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

        uint256 totalYield = 0;
        uint256 maxRepay = 0;
        uint256 maxYield = 0;

        for (uint256 i = 0; i < accounts.length; i++) {
            (maxRepay, maxYield) = ILiquidation(params.vault).checkLiquidation(address(this), accounts[i], params.collateralVault);
            totalYield += maxYield;

            // Step 3: Liquidate account in violation
            batchItems[i + 2] = IEVC.BatchItem({
                onBehalfOfAccount: address(this),
                targetContract: params.vault,
                value: 0,
                data: abi.encodeCall(
                ILiquidation.liquidate,
                    (accounts[i], params.collateralVault, maxRepay, 0) // TODO: adjust minimum collateral
                )
            });
        }

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[accounts.length + 2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.redeem, (totalYield, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[accounts.length + 3] = IEVC.BatchItem({    
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        batchItems[accounts.length + 4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(IRiskManager.disableController, ())
        });


        // Submit batch to EVC
        evc.batch(batchItems);

        return true;
    }
}